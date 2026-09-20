static int value;void external(void);
void Unrelated(void){external();}
int main(void){value++;return 0;}
