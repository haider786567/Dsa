class Solution:
    def factorial(self, n: int) -> int:
        fact = 1
        if n==0:
            return 1
        else:
            return n * self.factorial(n-1)
       

        pass
