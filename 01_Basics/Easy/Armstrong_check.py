class Solution:
    def armstrongNumber(self, n: int) -> bool:
        count = 0 
        check_count = n
        check_arm = n
        arm_num = 0 
        num = 0
        while check_count>0:
            count +=1
            check_count = check_count//10
        for i in range(1,count+1):
            num = check_arm%10
            arm_num = arm_num + (num ** count)
            check_arm = check_arm//10
        if(n == arm_num):
            return True
        else:
            return False
        


        pass