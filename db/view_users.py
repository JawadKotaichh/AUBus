from aubus_db import AUBusDB

db = AUBusDB("aubus.db")  # adjust path if needed
db.create_schema()  # safe if already created

# show columns
cols = [c[1] for c in db.conn.execute("PRAGMA table_info(users)")]
print("columns:", cols)

# show some rows
for r in db.conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 20"):
    print(dict(r))

db.close()
