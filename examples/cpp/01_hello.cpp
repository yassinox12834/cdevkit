// 01_hello.cpp: the smallest test. Works with every C++ standard from C++98.
// Prints the value of __cplusplus, which tells you which standard was used:
//   199711 = C++98, 201103 = C++11, 201402 = C++14, 201703 = C++17,
//   202002 = C++20, 202302 = C++23, above that = C++26 (draft)
#include <iostream>

int main() {
    std::cout << "Hello from C++!" << std::endl;
    std::cout << "__cplusplus = " << __cplusplus << std::endl;
    return 0;
}
