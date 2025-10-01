mysql -u root -p -h 127.0.0.1 -P 3306 -e "SELECT VERSION();"

python seed.py --schema demo_app --dry-run
--dry-run: connect to MySQL, look inside demo_app, read its tables and foreign keys, then print the FK-safe insert order without inserting anything.

pipenv run python seed.py --schema demo_app --truncate
--truncate (no --dry-run): do the same plan, then truncate and insert fake rows in that order.

pipenv run python seed.py --schema demo_app --rows default=1000,users=5000,orders=10000 --truncate
To specify number of rows for a table.