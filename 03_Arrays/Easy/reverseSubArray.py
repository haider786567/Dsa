# Read input, solve the problem, and print the answer.
class Solution:
	def reverseSubArray(self,arr,l,r):
		# code here
		left = l-1
		right = r-1
		if left >= right:
		    return arr
		else:
		    arr[left],arr[right] = arr[right],arr[left]
		    return self.reverseSubArray(arr,left+2,right)
