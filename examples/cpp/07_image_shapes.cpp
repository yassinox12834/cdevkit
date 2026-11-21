// 07_image_shapes.cpp: a tiny drawing library (pixels, lines, circles, rectangles)
// that draws a scene and saves shapes.bmp.
// Shows how shapes become pixels: a filled circle is "every pixel whose distance
// to the centre is at most r", and a line uses Bresenham's algorithm (integers only).
// Standard: C++17 or newer.
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <vector>

struct Rgb {
    std::uint8_t r, g, b;
};

class Canvas {
public:
    Canvas(int w, int h, Rgb background) : w_(w), h_(h), px_(static_cast<std::size_t>(w) * h, background) {}

    void set(int x, int y, Rgb c) {
        if (x >= 0 && y >= 0 && x < w_ && y < h_) {      // ignore pixels outside the image
            px_[static_cast<std::size_t>(y) * w_ + x] = c;
        }
    }

    void fill_rect(int x0, int y0, int w, int h, Rgb c) {
        for (int y = y0; y < y0 + h; ++y)
            for (int x = x0; x < x0 + w; ++x) set(x, y, c);
    }

    void fill_circle(int cx, int cy, int r, Rgb c) {
        for (int y = cy - r; y <= cy + r; ++y)
            for (int x = cx - r; x <= cx + r; ++x)
                if ((x - cx) * (x - cx) + (y - cy) * (y - cy) <= r * r) set(x, y, c);
    }

    void ring(int cx, int cy, int r, int thickness, Rgb c) {
        const int inner = (r - thickness) * (r - thickness);
        for (int y = cy - r; y <= cy + r; ++y)
            for (int x = cx - r; x <= cx + r; ++x) {
                const int d = (x - cx) * (x - cx) + (y - cy) * (y - cy);
                if (d <= r * r && d >= inner) set(x, y, c);
            }
    }

    // Bresenham's line algorithm.
    void line(int x0, int y0, int x1, int y1, Rgb c) {
        const int dx = std::abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
        const int dy = -std::abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
        int err = dx + dy;
        while (true) {
            set(x0, y0, c);
            if (x0 == x1 && y0 == y1) break;
            const int e2 = 2 * err;
            if (e2 >= dy) { err += dy; x0 += sx; }
            if (e2 <= dx) { err += dx; y0 += sy; }
        }
    }

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
                const Rgb& p = px_[static_cast<std::size_t>(y) * w_ + x];
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
    std::vector<Rgb> px_;
};

int main() {
    const Rgb black{8, 10, 14}, grid{24, 30, 40}, blue{59, 130, 246}, light{150, 190, 255}, white{235, 238, 242};
    Canvas canvas(640, 400, black);

    for (int x = 0; x < 640; x += 32) canvas.line(x, 0, x, 399, grid);     // background grid
    for (int y = 0; y < 400; y += 32) canvas.line(0, y, 639, y, grid);

    canvas.fill_rect(60, 250, 200, 90, blue);
    canvas.fill_circle(430, 170, 90, blue);
    canvas.ring(430, 170, 120, 6, light);
    canvas.fill_circle(160, 130, 40, white);

    for (int i = 0; i <= 12; ++i) {                                        // a fan of lines
        const double angle = 3.14159265358979 * i / 12;
        canvas.line(320, 390, 320 + static_cast<int>(150 * std::cos(angle)),
                    390 - static_cast<int>(150 * std::sin(angle)), light);
    }

    if (!canvas.save_bmp("shapes.bmp")) {
        std::cerr << "could not write shapes.bmp\n";
        return 1;
    }
    std::cout << "Saved shapes.bmp (640x400)\n";
    return 0;
}
