def kth_smallest(nums, k):
    if not nums or k < 1 or k > len(nums):
        return None
    
    # Using a sorted copy to find the k-th smallest element.
    # Duplicates are counted, so sorting is the most straightforward way.
    sorted_nums = sorted(nums)
    return sorted_nums[k - 1]
