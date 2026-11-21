// 04_cpp20_features.cpp: needs C++20. Choose c++17 in the launcher to see the
// compile errors, then c++20 to see it work. That is how you test the standard selector.
// Uses: concepts, ranges and views, std::span, designated initialisers.
#include <concepts>
#include <iostream>
#include <ranges>
#include <span>
#include <vector>

// A concept: a named requirement on a type.
template <typename T>
concept Number = std::integral<T> || std::floating_point<T>;

template <Number T>
T sum(std::span<const T> values) {
    T total{};
    for (T v : values) {
        total += v;
    }
    return total;
}

struct Settings {
    int width;
    int height;
    bool fullscreen;
};

int main() {
    std::vector<int> numbers = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};

    // Views are lazy: nothing is computed until the loop asks for it.
    auto squares_of_even = numbers
                         | std::views::filter([](int n) { return n % 2 == 0; })
                         | std::views::transform([](int n) { return n * n; });
    std::cout << "squares of even numbers:";
    for (int n : squares_of_even) {
        std::cout << ' ' << n;
    }
    std::cout << '\n';

    std::cout << "sum = " << sum<int>(numbers) << '\n';

    const Settings s{.width = 1280, .height = 720, .fullscreen = false};
    std::cout << "settings: " << s.width << 'x' << s.height
              << (s.fullscreen ? " fullscreen" : " windowed") << '\n';
    return 0;
}
