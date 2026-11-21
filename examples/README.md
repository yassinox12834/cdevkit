# Examples

Small programs to check that the toolchain and the launcher work. Open any file in the launcher (`Ctrl+O`), pick the standard shown below and press `F5`.

![The four images](../docs/examples.png)

## C

| File | Minimum standard | What it tests | You should see |
|---|---|---|---|
| `c/01_hello.c` | C89 | The compiler works; which standard was used | `Hello from C!` and `__STDC_VERSION__` |
| `c/02_input_sum.c` | C99 | Program input (`scanf`) | type `4 8 15 16 23 42` in the Input box: `sum = 108`, `mean = 18` |
| `c/03_pointers_structs.c` | C99 | Pointers, arrays, structs | `best player: Linus with 95` |
| `c/04_crash_demo.c` | C99 | The launcher's crash messages | put `null`, `divide`, `recurse` or `overflow` in Arguments |
| `c/05_image_gradient.c` | C99 | Writing a binary file | `gradient.bmp`, a colour gradient |
| `c/06_image_sierpinski.c` | C99 | Random numbers, fractals | `sierpinski.bmp`, the Sierpinski triangle |

## C++

| File | Minimum standard | What it tests | You should see |
|---|---|---|---|
| `cpp/01_hello.cpp` | C++98 | The compiler works; which standard was used | `Hello from C++!` and `__cplusplus` |
| `cpp/02_vectors_algorithms.cpp` | C++11 | `std::vector`, `std::sort`, lambdas | `sorted: 8 9 12 14 15 17 19` |
| `cpp/03_classes.cpp` | C++11 | Classes, `const`, operator overloading | `a . b = -5` |
| `cpp/04_cpp20_features.cpp` | C++20 | Concepts, ranges, `std::span` | `squares of even numbers: 4 16 36 64 100` |
| `cpp/05_cpp23_expected.cpp` | C++23 | `std::expected` (GCC 12+) | `1 / 0 failed: division by zero` |
| `cpp/06_image_mandelbrot.cpp` | C++17 | Heavy maths, optimisation | `mandelbrot.bmp` and the time taken |
| `cpp/07_image_shapes.cpp` | C++17 | Drawing lines and circles pixel by pixel | `shapes.bmp` |

The images are saved as `.bmp` in the folder the program runs from. With the launcher, that is the folder of the source file. `.bmp` opens without extra software on Windows, macOS and Linux.

## Three things worth trying

1. **The standard selector.** Open `cpp/04_cpp20_features.cpp`, choose `c++17` and run: you get errors such as `'concept' does not name a type`. Switch to `c++20` and it works.
2. **Optimisation.** Run `cpp/06_image_mandelbrot.cpp` with `-O0`, then with `-O3`, and compare the time it prints. Expect `-O3` to be several times faster.
3. **Crashes and undefined behaviour.** Run `c/04_crash_demo.c` with the argument `overflow`: it prints a meaningless number and carries on. Switch on **Stop on undefined behaviour** and run again: now it stops with an "illegal instruction" error. That switch catches bugs that would otherwise go unnoticed.
