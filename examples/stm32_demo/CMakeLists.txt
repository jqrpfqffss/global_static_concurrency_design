cmake_minimum_required(VERSION 3.16)
project(ecra_demo C)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_library(demo OBJECT main.c other.c)
