// 06_image_mandelbrot.cpp: renders the Mandelbrot set and saves mandelbrot.bmp.
// Try -O0 and then -O3 in the launcher and compare the time it prints.
//
// For each pixel, take the complex number c it represents and repeat z = z*z + c,
// starting from z = 0. If |z| stays small, c is in the set (black). Otherwise
// the colour shows how many steps it took to escape.
// Standard: C++17 or newer.
#include <chrono>
#include <cmath>
#include <algorithm>
#include <complex>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>

struct Rgb {
    std::uint8_t r, g, b;
};

class Image {
public:
    Image(int width, int height) : w_(width), h_(height), pixels_(static_cast<std::size_t>(width) * height) {}

    void set(int x, int y, Rgb c) { pixels_[static_cast<std::size_t>(y) * w_ + x] = c; }

    // 24-bit BMP: 54-byte header, then rows bottom-up in B, G, R order,
    // each row padded to a multiple of 4 bytes.
    bool save_bmp(const char* path) const {
        const int row_size = (3 * w_ + 3) & ~3;
        const std::uint32_t data_size = static_cast<std::uint32_t>(row_size * h_);
        unsigned char header[54] = {'B', 'M'};
        auto put32 = [&](int at, std::uint32_t v) {
            for (int i = 0; i < 4; ++i) header[at + i] = static_cast<unsigned char>(v >> (8 * i));
        };
        put32(2, 54 + data_size);
        put32(10, 54);
        put32(14, 40);
        put32(18, static_cast<std::uint32_t>(w_));
        put32(22, static_cast<std::uint32_t>(h_));
        header[26] = 1;
        header[28] = 24;
        put32(34, data_size);

        std::ofstream out(path, std::ios::binary);
        if (!out) return false;
        out.write(reinterpret_cast<const char*>(header), sizeof header);
        std::vector<char> row(static_cast<std::size_t>(row_size), 0);
        for (int y = h_ - 1; y >= 0; --y) {
            for (int x = 0; x < w_; ++x) {
                const Rgb& p = pixels_[static_cast<std::size_t>(y) * w_ + x];
                row[3 * x] = static_cast<char>(p.b);
                row[3 * x + 1] = static_cast<char>(p.g);
                row[3 * x + 2] = static_cast<char>(p.r);
            }
            out.write(row.data(), row_size);
        }
        return static_cast<bool>(out);
    }

private:
    int w_, h_;
    std::vector<Rgb> pixels_;
};

// Smooth blue palette: t goes from 0 (escaped at once) to 1 (escaped late).
Rgb palette(double t) {
    const auto channel = [](double v) { return static_cast<std::uint8_t>(255 * std::clamp(v, 0.0, 1.0)); };
    return {channel(t * t * 1.4), channel(t * 1.1), channel(0.25 + 0.9 * std::sqrt(t))};
}

int main() {
    constexpr int width = 900, height = 600, max_iter = 300;
    Image img(width, height);
    const auto start = std::chrono::steady_clock::now();

    for (int py = 0; py < height; ++py) {
        for (int px = 0; px < width; ++px) {
            const std::complex<double> c(-2.2 + 3.2 * px / width, -1.1 + 2.2 * py / height);
            std::complex<double> z = 0;
            int n = 0;
            while (std::norm(z) <= 4.0 && n < max_iter) {   // norm = |z|^2, avoids a sqrt
                z = z * z + c;
                ++n;
            }
            if (n == max_iter) {
                img.set(px, py, {0, 0, 0});
            } else {
                const double smooth = n + 1 - std::log2(std::log2(std::abs(z)));
                img.set(px, py, palette(std::sqrt(smooth / max_iter)));
            }
        }
    }

    const auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    if (!img.save_bmp("mandelbrot.bmp")) {
        std::cerr << "could not write mandelbrot.bmp\n";
        return 1;
    }
    std::cout << "Saved mandelbrot.bmp (" << width << 'x' << height << ") in " << ms << " ms\n";
    return 0;
}
