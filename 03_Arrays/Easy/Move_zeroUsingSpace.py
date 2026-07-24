class Solution:
    def moveZeros(self, arr):
        # write your code here
        result =[]
        for num in arr:
            if num == 0:
                result.append(0)
            else:
                result.insert(0,1)
        return result
