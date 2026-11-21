// 02_vectors_algorithms.cpp: std::vector, std::sort, lambdas and std::accumulate.
// Standard: C++11 or newer (uses auto, lambdas and range-based for).
#include <algorithm>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

int main() {
    std::vector<int> marks = {14, 9, 17, 12, 19, 8, 15};

    std::sort(marks.begin(), marks.end());
    std::cout << "sorted:";
    for (int m : marks) {
        std::cout << ' ' << m;
    }
    std::cout << '\n';

    const int total = std::accumulate(marks.begin(), marks.end(), 0);
    const double mean = static_cast<double>(total) / marks.size();
    std::cout << "mean = " << mean << '\n';

    // A lambda: a small function written inline. [] captures nothing here.
    const auto passed = std::count_if(marks.begin(), marks.end(), [](int m) { return m >= 10; });
    std::cout << passed << " of " << marks.size() << " marks are 10 or more\n";

    // Sort words by length, then alphabetically.
    std::vector<std::string> words = {"matrix", "gcc", "vector", "cmake", "ninja", "c"};
    std::sort(words.begin(), words.end(), [](const std::string& a, const std::string& b) {
        return a.size() != b.size() ? a.size() < b.size() : a < b;
    });
    std::cout << "by length:";
    for (const auto& w : words) {
        std::cout << ' ' << w;
    }
    std::cout << '\n';
    return 0;
}
