// rng.hpp

#pragma once

#include <iostream>
#include <iterator>
#include <random>
#include <sstream>
#include <string>
#include <algorithm>


static std::mt19937 mersenne(1729);
static std::uniform_int_distribution<int> uniform_int_dist(0, RAND_MAX);
static std::uniform_real_distribution<double> uniform_double_dist(0.0, 1.0);
static std::uniform_int_distribution<int> uniform_char_int_dist(0, 255);
// Using a range whose length is a power of 2 ensures that the bits of the
// integers drawn from the distribution are also uniformly distributed
static std::uniform_int_distribution<int> uniform_int_dist_pow2(0, 4095);

double randDouble();
int randInt();
int randCharInt();
int randBitInt();

void seedRNG(int s);

std::string getState();
void setState(std::string state);
