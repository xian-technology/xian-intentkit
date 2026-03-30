import os

os.environ.setdefault("REDIS_HOST", "localhost")

from intentkit.testing.xian_trade_social_workflow import main

if __name__ == "__main__":
    main()
