"""
class Task:
    def __init__(self, title, hours=0.0):   # runs when you create a Task
        self.title = title                  # each object stores its own title
        self.hours = hours
        self.status = "To Do"

t1 = Task("Write UAC for login")
t2 = Task("Review checkout flow", 2.0)
print(t1.title, t1.status)   # Write UAC for login To Do
print(t2.hours)              # 2.0  (t1 and t2 are separate objects)

"""

"""
class Task:
    def __init__(self, title):
        self.title = title
        self.status = "To Do"

    def start(self):
        self.status = "In Progress"

    def complete(self):
        self.status = "Done"

t = Task("Draft BRD")
t.start()          # Python passes t as self automatically
print(t.status)    # In Progress
"""

class Task:
    def __init__(self, title):
        self.title = title
        self.status = "In Progress"

    def complete(self):
        if self.status != "In Progress":
            raise ValueError("Only an In Progress task can be completed")
        self.status = "Done"

    def __str__(self):              # what print(task) shows
        return f"[{self.status}] {self.title}"

t = Task("Draft BRD")
print(t)                            # [To Do] Draft BRD
try:
    t.complete()
except ValueError as e:
    print("Blocked:", e)