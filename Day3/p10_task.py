class Task:
    def __init__(self, title, assignee, hours=0.0):
        self.title = title
        self.assignee = assignee
        self.hours = hours
        self.status = "To Do"

    def start(self):
        self.status = "In Progress"

    def complete(self):
        if self.status != "In Progress":
            raise ValueError("Only an In Progress task can be completed")
        self.status = "Done"

    def log_hours(self, h):
        if h <= 0:
            raise ValueError("Hours must be positive")
        self.hours += h

    def __str__(self):
        return f"[{self.status}] {self.title} – {self.hours} h ({self.assignee})"


class Project:
    def __init__(self, name):
        self.name = name
        self.tasks = []          # starts empty; add_task fills it

    def add_task(self, task):
        self.tasks.append(task) # put the task into self.tasks

    def total_hours(self):  # add up .hours of every task in self.tasks and return it
        return sum(task.hours for task in self.tasks) 

    def tasks_by_status(self, status):
        # TODO: return a NEW list with only the tasks whose .status == status
        return [task for task in self.tasks if task.status == status]


if __name__ == "__main__":
    p = Project("Checkout Revamp")

    t1 = Task("Draft BRD", "Ankur");               t1.start(); t1.log_hours(3.5)
    t2 = Task("Write UAC for login", "Priya");     t2.start(); t2.log_hours(2)
    t3 = Task("Review checkout flow", "Ankur");    t3.start(); t3.log_hours(1.5); t3.complete()
    t4 = Task("Prepare UAT test cases", "Rahul")   # still To Do, 0 hours

    for t in (t1, t2, t3, t4):
        p.add_task(t)

    print(f"Project: {p.name}")
    print(f"Total hours: {p.total_hours()}")
    print("In Progress:")
    for t in p.tasks_by_status("In Progress"):
        print("  ", t)