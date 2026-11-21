/* 06_image_sierpinski.c: draws the Sierpinski triangle with the "chaos game"
   and saves it as sierpinski.bmp.

   The chaos game: start anywhere, then repeat 200 000 times:
     pick one of the 3 corners at random, move halfway towards it, colour that pixel.
   A fractal appears, even though every step is random.
   Standard: C99 or newer. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define SIZE 512

static void put32(unsigned char *p, uint32_t v) {
    for (int i = 0; i < 4; i++) {
        p[i] = (unsigned char)(v >> (8 * i));
    }
}

static int save_bmp(const char *path, const unsigned char *rgb, int w, int h) {
    int row_size = (3 * w + 3) & ~3;
    uint32_t data_size = (uint32_t)(row_size * h);
    unsigned char header[54] = {'B', 'M'};
    put32(header + 2, 54 + data_size);
    put32(header + 10, 54);
    put32(header + 14, 40);
    put32(header + 18, (uint32_t)w);
    put32(header + 22, (uint32_t)h);
    header[26] = 1;
    header[28] = 24;
    put32(header + 34, data_size);

    FILE *f = fopen(path, "wb");
    if (!f) {
        perror(path);
        return 0;
    }
    fwrite(header, 1, sizeof header, f);
    unsigned char *row = calloc((size_t)row_size, 1);
    for (int y = h - 1; y >= 0; y--) {
        for (int x = 0; x < w; x++) {
            const unsigned char *px = rgb + 3 * (y * w + x);
            row[3 * x] = px[2];
            row[3 * x + 1] = px[1];
            row[3 * x + 2] = px[0];
        }
        fwrite(row, 1, (size_t)row_size, f);
    }
    free(row);
    fclose(f);
    return 1;
}

int main(void) {
    unsigned char *image = calloc(3 * SIZE * SIZE, 1);  /* calloc: starts black */
    if (!image) {
        return 1;
    }
    const double cx[3] = {SIZE / 2.0, 8, SIZE - 8};     /* the three corners */
    const double cy[3] = {8, SIZE - 8, SIZE - 8};
    double x = 0, y = 0;

    srand(2026);                                         /* fixed seed: same image every run */
    for (int i = 0; i < 200000; i++) {
        int corner = rand() % 3;
        x = (x + cx[corner]) / 2;
        y = (y + cy[corner]) / 2;
        if (i < 20) {
            continue;                                    /* skip the first steps: not on the fractal yet */
        }
        unsigned char *px = image + 3 * ((int)y * SIZE + (int)x);
        px[0] = (unsigned char)(80 + 175 * (corner == 0));   /* colour by the chosen corner */
        px[1] = (unsigned char)(80 + 175 * (corner == 1));
        px[2] = 255;
    }
    int ok = save_bmp("sierpinski.bmp", image, SIZE, SIZE);
    free(image);
    if (ok) {
        printf("Saved sierpinski.bmp (%dx%d).\n", SIZE, SIZE);
    }
    return ok ? 0 : 1;
}
