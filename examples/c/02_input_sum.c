/* 02_input_sum.c: reads numbers until the end of input and prints their sum and mean.
   Tests program input. In the launcher, either type numbers in the Input box
   (for example: 4 8 15 16 23 42) or switch on "Run in a separate terminal".
   Standard: C99 or newer. */
#include <stdio.h>

int main(void) {
    double value, sum = 0.0;
    int count = 0;

    printf("Enter numbers (end with Ctrl+D on Linux/macOS, Ctrl+Z then Enter on Windows):\n");
    while (scanf("%lf", &value) == 1) {
        sum += value;
        count++;
    }

    if (count == 0) {
        printf("No numbers read.\n");
        return 1;
    }
    printf("count = %d\nsum   = %g\nmean  = %g\n", count, sum, sum / count);
    return 0;
}
