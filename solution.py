class Solution:
    def countDigits(self, n: int) -> int:
        digits = [int(d) for d in str(n)]
        return len(digits)
        pass