was inserting child rows (order_items) before their parents (orders, products), and

cmd_query self._cmysql.query( ~~~~~~~~~~~~~~~~~~^ query, ^^^^^^ ...<3 lines>... query_attrs=self.query_attrs, ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ) ^ _mysql_connector.MySQLInterfaceError: Cannot add or update a child row: a foreign key constraint fails (demo_app.order_items, CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE ON UPDATE CASCADE) The above exception was the direct cause of the following exception: Traceback (most recent call last): File "C:\Users\Abdul Hannan\.virtualenvs\Sql_Agent_Naive-az-4L5-s\Lib\site-packages\sqlalchemy\engine\base.py", line 1967, in _exec_single_context self.dialect.do_execute( ~~~~~~~~~~~~~~~~~~~~~~~^ cursor, str_statement, effective_parameters, context
------------------------------------------------------------------
inserting random values into AUTO_INCREMENT PKs and FK columns (e.g., order_items.order_id=409 when no orders.id=409 exists).

parameters being sent to the INSERT:

[parameters: {
  'id': 1824,                      <- explicitly setting AI PK
  'order_id': 409,                 <- FK to orders.id (doesn’t exist)
  'product_id': 4506,              <- FK to products.id (doesn’t exist)
  'quantity': 4012,
  'unit_price': Decimal('2340.53'),
  'created_at': datetime.datetime(2024, 2, 10, 13, 54, 25)
}]

failing statement shows we were inserting into order_items (the child) first:
INSERT INTO `demo_app`.`order_items`
(`id`, `order_id`, `product_id`, `quantity`, `unit_price`, `created_at`)
VALUES (%(id)s, %(order_id)s, %(product_id)s, %(quantity)s, %(unit_price)s, %(created_at)s)
-----------------------------------------------------------------
 Faker sometimes generates the same email twice, so we need to make email (and other unique columns like sku, username) guaranteed unique when the column has a UNIQUE index.


--------------------------------------
Streamlit internally uses certain contexts when running scripts in "server mode," and the warning simply indicates that it’s running in a different execution mode
Error:
streamlit run sql_agent_gemini_app.py [ARGUMENTS]
2025-10-01 17:18:15.611 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.