// 03_classes.cpp: a class with a constructor, const methods and operator overloading.
// Standard: C++11 or newer.
#include <cmath>
#include <iostream>

class Vec2 {
public:
    Vec2(double x, double y) : x_(x), y_(y) {}

    double length() const { return std::sqrt(x_ * x_ + y_ * y_); }
    double dot(const Vec2& other) const { return x_ * other.x_ + y_ * other.y_; }

    Vec2 operator+(const Vec2& other) const { return Vec2(x_ + other.x_, y_ + other.y_); }
    Vec2 operator*(double k) const { return Vec2(x_ * k, y_ * k); }

    friend std::ostream& operator<<(std::ostream& out, const Vec2& v) {
        return out << '(' << v.x_ << ", " << v.y_ << ')';
    }

private:
    double x_;
    double y_;
};

int main() {
    const Vec2 a(3, 4);
    const Vec2 b(1, -2);
    std::cout << "a = " << a << ", |a| = " << a.length() << '\n';
    std::cout << "a + b = " << (a + b) << '\n';
    std::cout << "a * 2 = " << (a * 2) << '\n';
    std::cout << "a . b = " << a.dot(b) << '\n';
    return 0;
}
