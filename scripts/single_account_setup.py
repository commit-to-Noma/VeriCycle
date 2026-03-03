import sqlite3
import json

con = sqlite3.connect("vericycle.db")
cur = con.cursor()
cur.execute("update user set role='admin' where email=?", ("test@gmail.com",))
con.commit()
row = cur.execute(
    "select hedera_account_id, hedera_private_key, role from user where email='test@gmail.com'"
).fetchone()
print("OK: test@gmail.com is now admin")
print(json.dumps({"id": row[0], "key": row[1], "role": row[2]}))
