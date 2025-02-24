import sqlite3

# Connect to database
conn = sqlite3.connect("instance/database.db")
cursor = conn.cursor()

# View all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables:", tables)

# Query pollution reports
cursor.execute("SELECT * FROM user;")
reports = cursor.fetchall()

for report in reports:
    print(report)

# Close connection
conn.close()
