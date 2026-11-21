/* 03_pointers_structs.c: pointers, arrays and structs, the core of C.
   Standard: C99 or newer (declares variables inside for loops). */
#include <stdio.h>
#include <string.h>

typedef struct {
    char name[32];
    int score;
} Player;

/* Swaps two ints through their addresses. */
static void swap(int *a, int *b) {
    int tmp = *a;
    *a = *b;
    *b = tmp;
}

/* Returns a pointer to the player with the highest score. */
static const Player *best(const Player *players, size_t n) {
    const Player *top = &players[0];
    for (size_t i = 1; i < n; i++) {
        if (players[i].score > top->score) {
            top = &players[i];
        }
    }
    return top;
}

int main(void) {
    int x = 3, y = 7;
    swap(&x, &y);
    printf("after swap: x = %d, y = %d\n", x, y);

    int numbers[5] = {10, 20, 30, 40, 50};
    int *p = numbers;                       /* the array name decays to a pointer */
    printf("numbers[2] = %d, *(p + 2) = %d\n", numbers[2], *(p + 2));

    Player team[3];
    const char *names[3] = {"Ada", "Linus", "Grace"};
    const int scores[3] = {88, 95, 91};
    for (int i = 0; i < 3; i++) {
        strncpy(team[i].name, names[i], sizeof team[i].name - 1);
        team[i].name[sizeof team[i].name - 1] = '\0';
        team[i].score = scores[i];
    }
    const Player *top = best(team, 3);
    printf("best player: %s with %d\n", top->name, top->score);
    printf("sizeof(Player) = %zu bytes\n", sizeof(Player));
    return 0;
}
