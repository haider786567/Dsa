#Write your code here
n = int(input())


def calculate_sum(n):
    sum = 0 
    for i in range(n):
        if(n==0):
            break
        else:
            num= n%10
            sum+=num
            n = n//10
    print(sum)
   

calculate_sum(n)
