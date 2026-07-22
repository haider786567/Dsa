
def secondLargest_element(arr):
    greatest_element = max(arr)
    second_greatest_element = float("-inf")
    for i in range(len(arr)):
        if arr[i] <greatest_element and arr[i] >second_greatest_element:
            second_greatest_element = arr[i]
    print(f"Second greatest element = {second_greatest_element}")
    

n = int(input())
arr = list(map(int, input().split()))
secondLargest_element(arr)
