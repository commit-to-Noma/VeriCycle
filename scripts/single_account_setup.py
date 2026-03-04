import sqlite3
import json

con = sqlite3.connect("vericycle.db")
cur = con.cursor()
cur.execute("update user set role='admin' where email=?", ("test@gmail.com",))
con.commit()
row = cur.execute(
    "select hedera_account_id, hedera_private_key, hedera_private_key_encrypted, role from user where email='test@gmail.com'"
).fetchone()
print("OK: test@gmail.com is now admin")
print(json.dumps({
    "id": row[0],
    "has_plain_key": bool(row[1]),
    "has_encrypted_key": bool(row[2]),
    "role": row[3]
}))
