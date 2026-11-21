// 05_cpp23_expected.cpp: needs C++23 (GCC 12 or newer).
// std::expected holds either a value or an error, so a function can fail
// without exceptions and without a special "error number".
#include <expected>
#include <iostream>
#include <string>

std::expected<double, std::string> safe_divide(double a, double b) {
    if (b == 0.0) {
        return std::unexpected("division by zero");
    }
    return a / b;
}

void show(double a, double b) {
    const auto result = safe_divide(a, b);
    if (result) {
        std::cout << a << " / " << b << " = " << *result << '\n';
    } else {
        std::cout << a << " / " << b << " failed: " << result.error() << '\n';
    }
}

int main() {
    show(10, 4);
    show(1, 0);
    // value_or: use a fallback when there is an error.
    std::cout << "with fallback: " << safe_divide(5, 0).value_or(-1) << '\n';
    return 0;
}
