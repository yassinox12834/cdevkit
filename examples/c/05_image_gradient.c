/* 05_image_gradient.c: draws a colour gradient and saves it as gradient.bmp.
   The image is saved in the folder the program runs from: with the launcher,
   that is the folder of this source file.

   How a 24-bit BMP file works:
     - a 54-byte header (file size, width, height, bits per pixel...)
     - then the pixels, 3 bytes each in the order Blue, Green, Red
     - rows are stored from the BOTTOM row up, and each row is padded
       with zero bytes so its length is a multiple of 4.
   Standard: C99 or newer. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define WIDTH 512
#define HEIGHT 256

/* Writes the 32-bit value v as 4 bytes, least significant first (little-endian). */
static void put32(unsigned char *p, uint32_t v) {
    p[0] = (unsigned char)(v);
    p[1] = (unsigned char)(v >> 8);
    p[2] = (unsigned char)(v >> 16);
    p[3] = (unsigned char)(v >> 24);
}

static int save_bmp(const char *path, const unsigned char *rgb, int w, int h) {
    int row_size = (3 * w + 3) & ~3;                 /* round up to a multiple of 4 */
    uint32_t data_size = (uint32_t)(row_size * h);
    unsigned char header[54] = {'B', 'M'};
    put32(header + 2, 54 + data_size);              /* total file size */
    put32(header + 10, 54);                         /* where the pixels start */
    put32(header + 14, 40);                         /* size of the info header */
    put32(header + 18, (uint32_t)w);
    put32(header + 22, (uint32_t)h);
    header[26] = 1;                                 /* one colour plane */
    header[28] = 24;                                /* 24 bits per pixel */
    put32(header + 34, data_size);

    FILE *f = fopen(path, "wb");
    if (!f) {
        perror(path);
        return 0;
    }
    fwrite(header, 1, sizeof header, f);
    unsigned char *row = calloc((size_t)row_size, 1);
    for (int y = h - 1; y >= 0; y--) {              /* bottom row first */
        for (int x = 0; x < w; x++) {
            const unsigned char *px = rgb + 3 * (y * w + x);
            row[3 * x + 0] = px[2];                 /* B */
            row[3 * x + 1] = px[1];                 /* G */
            row[3 * x + 2] = px[0];                 /* R */
        }
        fwrite(row, 1, (size_t)row_size, f);
    }
    free(row);
    fclose(f);
    return 1;
}

int main(void) {
    unsigned char *image = malloc(3 * WIDTH * HEIGHT);
    if (!image) {
        return 1;
    }
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            unsigned char *px = image + 3 * (y * WIDTH + x);
            px[0] = (unsigned char)(255 * x / (WIDTH - 1));        /* red grows left to right */
            px[1] = (unsigned char)(255 * y / (HEIGHT - 1));       /* green grows top to bottom */
            px[2] = 160;                                           /* constant blue */
        }
    }
    int ok = save_bmp("gradient.bmp", image, WIDTH, HEIGHT);
    free(image);
    if (ok) {
        printf("Saved gradient.bmp (%dx%d). It is in the current folder.\n", WIDTH, HEIGHT);
    }
    return ok ? 0 : 1;
}
