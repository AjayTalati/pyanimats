#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# evolve.py

"""Implements the genetic algorithm."""

import os
import pickle
import random
from copy import deepcopy
from time import time

import numpy as np
from deap import base, tools

import c_animat
import fitness_functions
import utils
from __about__ import __version__
from constants import MINUTES
from phylogeny import Phylogeny


class Evolution:

    """An evolutionary simulation."""

    def __init__(self, experiment, population, logbook, python_rng_state,
                 c_rng_state, generation):
        self.experiment = experiment
        self.population = population
        self.logbook = logbook
        self.python_rng_state = python_rng_state
        self.c_rng_state = c_rng_state
        self.elapsed = 0
        # Get our own RNG.
        self.random = random.Random()
        self.generation = generation
        # Get the generational interval at which to print the evolution status.
        self.status_interval = experiment.status_interval
        if self.status_interval <= 0:
            self.status_interval = float('inf')
        # Get the time interval at which to save checkpoints.
        self.checkpoint_time_interval = experiment.checkpoint_frequency * MINUTES
        if self.checkpoint_time_interval <= 0:
            self.checkpoint_time_interval = float('inf')
        # Get the generational interval at which to save checkpoints.
        if experiment.min_checkpoints <= 0:
            self.checkpoint_generation_interval = float('inf')
        else:
            self.checkpoint_generation_interval = (
                experiment.ngen // experiment.min_checkpoints)
        # Create statistics trackers.
        fitness_stats = tools.Statistics(key=lambda animat: animat.fitness.raw)
        fitness_stats.register('max', np.max)
        real_fitness_stats = tools.Statistics(key=lambda animat: animat.fitness.value)
        real_fitness_stats.register('max', np.max)
        correct_stats = tools.Statistics(key=lambda animat: (animat.correct,
                                                                animat.incorrect))
        correct_stats.register('correct', lambda x: np.max(x, 0)[0])
        correct_stats.register('incorrect', lambda x: np.max(x, 0)[1])
        # Stats objects for alternate matching measures.
        alt_fitness_stats = tools.Statistics(key=lambda animat: animat.alt_fitness)
        alt_fitness_stats.register('weighted', lambda x: np.max(x, 0)[0])
        alt_fitness_stats.register('unweighted', lambda x: np.max(x, 0)[1])
        # Initialize a MultiStatistics object for convenience that allows for only
        # one call to `compile`.
        if self.experiment.fitness_function == 'mat':
            self.mstats = tools.MultiStatistics(correct=correct_stats,
                                                fitness=fitness_stats,
                                                real_fitness=real_fitness_stats,
                                                alt_fitness=alt_fitness_stats)
        else:
            self.mstats = tools.MultiStatistics(correct=correct_stats, fitness=fitness_stats,
                                                real_fitness=real_fitness_stats)
        # Initialize evaluate function.
        fitness_function = fitness_functions.__dict__[experiment.fitness_function]

        def multi_fit_evaluate(pop, gen):
            fitnesses = map(fitness_function, pop)
            for animat, fitness in zip(pop, fitnesses):
                animat.fitness.set(fitness[0])
                animat.alt_fitness = fitness[1:]

        def single_fit_evaluate(pop, gen):
            fitnesses = map(fitness_function, pop)
            for animat, fitness in zip(pop, fitnesses):
                animat.fitness.set(fitness)
        self.evaluate = (multi_fit_evaluate if self.experiment.fitness_function
                         == 'mat' else single_fit_evaluate)

    def select(self, animats, k):
        """Select *k* animats from a list of animats.

        Uses fitness-proportionate selection.

        Args:
            animats (Iterable): The population of animats to select from.
            k (int): The number of animats to select from the population.

        Returns
            list: The selected animats.
        """
        max_fitness = max(animat.fitness.value for animat in animats)
        chosen = []
        for i in range(k):
            done = False
            while not done:
                candidate = self.random.choice(animats)
                done = self.random.random() <= (candidate.fitness.value /
                                                max_fitness)
            chosen.append(candidate)
        return chosen

    def print_status(self, line, elapsed):
        """Print a status uptdate to the screen."""
        print('[Seed {}] {}{}'.format(self.experiment.rng_seed, line,
                                      utils.compress(elapsed)))

    def record(self, population, gen):
        if gen % self.experiment.log_interval == 0:
            record = self.mstats.compile(population)
            self.logbook.record(gen=gen, **record)

    def new_gen(self, population, gen):
        # Update generation number.
        self.generation = gen
        # Selection.
        population = self.select(population, len(population))
        # Cloning.
        # TODO: why does directly cloning the population prevent evolution?!
        offspring = [deepcopy(x) for x in population]
        # Variation.
        for i, animat in enumerate(offspring):
            # Update parent reference.
            animat.parent = population[i]
            # Update generation number.
            animat.gen = gen
            # Mutate.
            animat.mutate()
        # Evaluation.
        self.evaluate(offspring, gen)
        # Recording.
        self.record(offspring, gen)
        return offspring

    def run(self, checkpoint_file):
        """Evolve."""
        # Set the random number generator states.
        self.random.setstate(self.python_rng_state)
        c_animat.set_rng_state(self.c_rng_state)

        # Initial evalutation.
        if self.generation == 0:
            self.evaluate(self.population, 0)
            self.record(self.population, 0)
            # Print first lines of the logbook.
            if 0 < self.status_interval < float('inf'):
                first_lines = str(self.logbook).split('\n')
                header_lines = [
                    '[Seed {}] {}'.format(self.experiment.rng_seed, l)
                    for l in first_lines[:-1]]
                print('\n' + '\n'.join(header_lines))

        last_status, last_checkpoint = time(), time()

        for gen in range(self.generation + 1, self.experiment.ngen + 1):
            self.generation = gen
            # Evolution.
            self.population = self.new_gen(self.population, gen)
            # Reporting.
            if gen % self.status_interval == 0:
                # Get time since last report was printed.
                elapsed_since_last_status = time() - last_status
                self.print_status(self.logbook.__str__(startindex=gen),
                                  elapsed_since_last_status)
                last_status = time()
            # Checkpointing.
            elapsed_since_last_checkpoint = time() - last_checkpoint
            if elapsed_since_last_checkpoint >= self.checkpoint_time_interval:
                print('[Seed {}] Saving checkpoint... '.format(
                    self.experiment.rng_seed), end='')
                self.elapsed += time() - last_checkpoint
                self.save_checkpoint(checkpoint_file)
                last_checkpoint = time()
                print('done.')

        self.elapsed += time() - last_checkpoint

        return self.elapsed

    def to_json(self, all_lineages=False):
        # Determine the generational interval.
        gen_interval = max(
            self.experiment.ngen // self.experiment.num_samples, 1)
        # Get the lineage(s).
        if not all_lineages:
            fittest = max(self.population, key=lambda a: a.fitness.value)
            lineage = fittest.serializable_lineage(interval=gen_interval,
                                                   experiment=False)
        else:
            lineage = [a.serializable_lineage(interval=gen_interval,
                                              experiment=False)
                       for a in self.population]
        # Set up the JSON object.
        json_data = {
            'experiment': self.experiment.serializable(),
            'lineage': lineage,
            'logbook': {
                'gen': self.logbook.select('gen'),
                'fitness': self.logbook.chapters['fitness'].select('max'),
                'correct': self.logbook.chapters['correct'].select('correct'),
                'incorrect': (self.logbook.chapters['correct']
                              .select('incorrect')),
            },
            'metadata': {
                'elapsed': round(self.elapsed, 2),
                'version': utils.get_version(),
            },
        }
        return json_data

    def save_checkpoint(self, filepath):
        """Save a checkpoint that can be used to resume evolution.

        Pickles the evolution state and saves to ``filepath``.
        """
        data = {
            'experiment': self.experiment,
            'generation': self.generation,
            # Save the population as a Phylogeny to recover lineages later.
            'population': Phylogeny(self.population),
            'logbook': self.logbook,
            'python_rng_state': self.random.getstate(),
            'c_rng_state': c_animat.get_rng_state(),
            'metadata': {
                'elapsed': round(self.elapsed, 2),
                'version': utils.get_version(),
            },
        }
        with open(filepath, 'wb') as f:
            pickle.dump(data, f)


def load_checkpoint(filepath):
    """Load an evolution from a checkpoint file.

    Returns the checkpoint as a dictionary whose values are suitable for
    initializing a new ``Evolution`` object.
    """
    with open(filepath, 'rb') as f:
        checkpoint = pickle.load(f)
    # Convert the loaded Phylogeny back to a normal list.
    checkpoint['population'] = list(checkpoint['population'])
    return checkpoint
