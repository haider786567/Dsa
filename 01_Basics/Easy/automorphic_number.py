#Write your code here
n = int(input())
def Count_num(n):
    count = 0 
    while(n > 0):
        count +=1
        n = n // 10
    return count

def automorphic_check(n):
    square_n = n ** 2 
    digit_count = Count_num(n)
    if(square_n % (10**digit_count )== n):
        print("Yes")
    else:
        print("No")

automorphic_check(n)