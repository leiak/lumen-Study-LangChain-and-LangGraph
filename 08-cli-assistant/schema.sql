-- schema.sql — DataAgent demo 用 MySQL 参考 schema
--
-- 跑法 (任选其一):
--   mysql -u root -p < schema.sql
--   mysql -u your_user -p your_db < schema.sql     (-- 然后手动 USE cli_demo;)
--
-- 加载后, .env 设置 MYSQL_DATABASE=cli_demo, 启动 CLI 问 "北京有几个用户"
-- → 派 DataAgent → list_tables → describe_table → run_sql → HITL 审批 → 结果
--
-- 注意: 这是 reference schema, 不带自动 seed 逻辑 (避免破坏用户的真实 DB).
-- 用户自行 mysql < schema.sql 加载. 已加载过的表用 IF NOT EXISTS, 重复跑安全.

CREATE DATABASE IF NOT EXISTS cli_demo
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE cli_demo;

-- ============================================================
-- 用户表
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(50) NOT NULL COMMENT '用户姓名',
  city VARCHAR(30) COMMENT '常驻城市',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- ============================================================
-- 订单表
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL COMMENT '下单用户 ID',
  amount DECIMAL(10, 2) NOT NULL COMMENT '订单金额',
  status ENUM('paid', 'shipped', 'delivered', 'refunded')
    DEFAULT 'paid' COMMENT '订单状态',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '下单时间',
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';

-- ============================================================
-- 订单明细表 (一对多: orders → order_items)
-- ============================================================
CREATE TABLE IF NOT EXISTS order_items (
  id INT PRIMARY KEY AUTO_INCREMENT,
  order_id INT NOT NULL COMMENT '所属订单 ID',
  product VARCHAR(100) NOT NULL COMMENT '商品名称',
  quantity INT NOT NULL DEFAULT 1 COMMENT '数量',
  FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细';

-- ============================================================
-- 示例数据 (5 用户 / 6 订单 / 6 明细) — 让 DataAgent 一开始就能出有意义的查询
-- ============================================================
-- 重复跑安全: 先清, 再插
DELETE FROM order_items;
DELETE FROM orders;
DELETE FROM users;

INSERT INTO users (name, city) VALUES
  ('张三', '北京'),
  ('李四', '上海'),
  ('王五', '广州'),
  ('赵六', '深圳'),
  ('钱七', '杭州');

INSERT INTO orders (user_id, amount, status) VALUES
  (1, 199.00, 'paid'),
  (1, 299.00, 'shipped'),
  (2, 150.00, 'delivered'),
  (3, 450.00, 'paid'),
  (4, 89.00, 'refunded'),
  (5, 1200.00, 'paid');

INSERT INTO order_items (order_id, product, quantity) VALUES
  (1, 'LangChain 课程', 1),
  (2, 'LangGraph 课程', 1),
  (3, 'AI Agent 实战', 1),
  (4, 'Python 进阶', 1),
  (5, 'LangChain 课程', 1),
  (6, '全套大礼包', 1);