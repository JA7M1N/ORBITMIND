import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='orbitalmind', user='postgres', password='postgres')
cur = conn.cursor()
cur.execute('SELECT version()')
print('DB:', cur.fetchone()[0].split(',')[0])
cur.execute('SELECT extname, extversion FROM pg_extension ORDER BY extname')
rows = cur.fetchall()
print('Installed extensions:')
for r in rows:
    print(' ', r[0], r[1])
conn.close()
