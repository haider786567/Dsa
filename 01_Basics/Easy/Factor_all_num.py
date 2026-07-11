n = int(input())


def Factor(n):
    
    for i in range(1,n+1):
        if(n%i==0):
            print(i, end = ' ')
Factor(n)