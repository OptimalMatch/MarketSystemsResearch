# Market Systems Research
[![Watch the demo video](docs/images/screenshot_home.png)](https://youtu.be/dc28jhKj8og?hd=1 "Demo")

## Installation and Running
1. Clone this repository

2. Set up Python environment:
```bash
# Install Miniconda if you haven't already
# Visit https://docs.conda.io/en/latest/miniconda.html for installation instructions

# Create and activate conda environment
conda create -n market_systems python=3.9
conda activate market_systems

# Install dependencies
pip install -r requirements.txt
```

3. Run the visualization server:
```bash
python VisualServer.py
```

4. Open your browser to [http://localhost:8084/](http://localhost:8084/)


# Exchange System Design Document

## 1. System Overview

The Exchange System is a Python-based implementation of a security trading platform that supports order matching, balance management, and trade settlement. The system implements a price-time priority matching algorithm and maintains separate orderbooks for different securities.

The current system uses 1-2 CPU cores for order matching and trade settlement, and 1-2 CPU cores for visualization. The number of CPU cores can be adjusted in the configuration file.

Out of the gate, we see 85k orders/sec and 34k trades/sec. It stabilizes at around 40k orders/sec and 20k trades/sec.  HFT systems can reach up to 100k orders/sec and 50k trades/sec for the one ticker symbol.  If we separated the metrics capture further, we could reach that level.

Example Output:

      Performance Metrics:
      Memory Usage: 100.89 MB
      Order Throughput: 85395.00 orders/sec
      Trade Throughput: 34595.00 trades/sec
      
      Rush Statistics:
      Total Orders: 85440
      Successful Orders: 85440
      Failed Orders: 0
      Current Price: 101.00288946853985
      Price Movement: 1.00%
      Volume: 1219900
      Total Trades: 34627


## 2. Core Components

### 2.1 Market
The Market class serves as the main entry point and coordinator for the exchange system. It:
- Manages multiple orderbooks for different securities
- Tracks user balances
- Validates orders
- Processes trades
- Handles deposits and withdrawals

### 2.2 OrderBook
The OrderBook class manages the order matching and trade execution for a single security. It:
- Maintains separate lists for buy (bid) and sell (ask) orders
- Implements price-time priority matching
- Records executed trades
- Provides market depth information

### 2.3 Order
The Order class represents a single order in the system with properties:
- Unique identifier
- Owner information
- Side (buy/sell)
- Price and size
- Fill amount
- Creation timestamp

### 2.4 Trade
The Trade class represents an executed trade with properties:
- Unique identifier
- Security identifier
- Buyer and seller information
- Price and size
- Execution timestamp

## 3. Key Processes

### 3.1 Order Placement Process
1. Client submits order to Market
2. Market validates user balance
3. Market creates Order object
4. Order is submitted to appropriate OrderBook
5. OrderBook attempts to match order
6. If matches found, trades are created and processed
7. If unmatched quantity remains, order is added to book

### 3.2 Order Matching Algorithm
1. For buy orders:
   - Match against asks in ascending price order
   - Match if ask price ≤ buy price
2. For sell orders:
   - Match against bids in descending price order
   - Match if bid price ≥ sell price
3. Within same price level, orders are matched in time priority

### 3.3 Trade Settlement Process
1. Trade is created with matched quantity
2. Buyer's cash balance is decreased
3. Seller's cash balance is increased
4. Buyer receives securities
5. Seller's security balance is decreased
6. Order fill amounts are updated
7. Fully filled orders are removed from book

## 4. State Management

### 4.1 Order States
- Created: Initial state after order creation
- Matching: Order is being matched against the book
- Active: Order is in the book awaiting matches
- PartiallyFilled: Order has some fills but remains active
- Filled: Order is completely filled
- Cancelled: Order was cancelled by user

### 4.2 Balance Management
- Balances are tracked per user and security
- Cash balances are tracked with 'cash' as security_id
- Balance validation occurs before order placement
- Balances are updated atomically during trade settlement

## 5. Data Structures

### 5.1 Orderbook Storage
- Bids: List sorted by price (descending) and time
- Asks: List sorted by price (ascending) and time
- Trades: List of executed trades

### 5.2 Balance Storage
- Two-level dictionary: user_id -> security_id -> amount
- Decimal type used for precise calculations

## 6. Error Handling

### 6.1 Validation Checks
- Security existence
- Sufficient balance
- Valid order parameters
- Order ownership for cancellations

### 6.2 Error Conditions
- Invalid security identifier
- Insufficient balance
- Invalid order parameters
- Unauthorized cancellation
- Order not found

## 7. Future Enhancements

### 7.1 Potential Improvements
- Persistent storage for orders and trades
- Support for different order types (market, limit, stop)
- Fee calculation and collection
- Advanced matching algorithms
- Real-time market data distribution
- Risk management systems

### 7.2 Performance Optimizations
- Index structures for order lookup
- Optimized data structures for order matching
- Caching of market depth calculations
- Batch processing of trades
- Parallel order matching

## 8. Diagrams

The system is documented with three types of UML diagrams:

1. Class Diagram: Shows the static structure and relationships between classes


```mermaid
classDiagram
    class Market {
        -Dict orderbooks
        -Dict balances
        -Logger logger
        +create_orderbook(security_id)
        +place_order(owner_id, security_id, side, price, size)
        +get_market_depth(security_id, levels)
        +get_balance(user_id, security_id)
        +deposit(user_id, security_id, amount)
        +withdraw(user_id, security_id, amount)
        -_validate_balance(owner_id, security_id, side, price, size)
        -_process_trades(trades)
    }
    
    class OrderBook {
        -String security_id
        -List bids
        -List asks
        -List trades
        +add_order(order)
        +cancel_order(order_id)
        +get_market_price()
        -_match_order(order)
        -_add_bid(order)
        -_add_ask(order)
    }
    
    class Order {
        +String id
        +String owner_id
        +OrderSide side
        +Decimal price
        +Decimal size
        +Decimal filled
        +DateTime created_at
        +String security_id
        +create(owner_id, side, price, size, security_id)
    }
    
    class Trade {
        +String id
        +String security_id
        +String buyer_id
        +String seller_id
        +Decimal price
        +Decimal size
        +DateTime timestamp
        +create(security_id, buyer_id, seller_id, price, size)
    }
    
    class OrderSide {
        <<enumeration>>
        BUY
        SELL
    }
    
    Market "1" --> "*" OrderBook : contains
    OrderBook "1" --> "*" Order : manages
    OrderBook "1" --> "*" Trade : records
    Order --> "1" OrderSide : has
```
2. Sequence Diagram: Illustrates the order placement and matching process

```mermaid
sequenceDiagram
    participant C as Client
    participant M as Market
    participant OB as OrderBook
    participant O as Order

    C->>M: place_order(params)
    activate M
    M->>M: _validate_balance()
    M->>O: Order.create()
    activate O
    O-->>M: new Order
    deactivate O
    M->>OB: add_order(order)
    activate OB
    OB->>OB: _match_order(order)
    
    alt Has Matching Orders
        OB->>OB: Create Trade(s)
        OB-->>M: trades
        M->>M: _process_trades(trades)
    else No Matches
        OB->>OB: _add_bid/ask(order)
        OB-->>M: empty trades list
    end
    
    deactivate OB
    M-->>C: trades
    deactivate M
```
3. State Diagram: Depicts the lifecycle of an order in the system


```mermaid
stateDiagram-v2
    [*] --> Created: Order Created
    Created --> Matching: Validation Passed
    
    Matching --> PartiallyFilled: Partial Match Found
    Matching --> Filled: Full Match Found
    Matching --> Active: No Match Found
    
    PartiallyFilled --> Active: Add to Book
    PartiallyFilled --> Filled: Full Match Found
    
    Active --> PartiallyFilled: Partial Match Found
    Active --> Filled: Full Match Found
    Active --> Cancelled: Cancel Order
    
    Filled --> [*]
    Cancelled --> [*]
```

These diagrams provide different views of the system's architecture and behavior.

For simulation, below we have the logic flow used when simulating market situations such as a intra-day bull run where we can observe a market maker's effect countering the run.

Market Maker logic flow:
```mermaid
flowchart TD
    A[Start Market Maker] --> B{Get Market Depth}
    B -->|Depth Available| C[Calculate Mid Price]
    B -->|No Depth| D[Use Fallback Price]
    C --> E{Analyze Market Condition}
    D --> E
    E -->|Bull Run| F[Increase Sell Size<br>Reduce Buy Size]
    E -->|Bear Dip| G[Increase Buy Size<br>Reduce Sell Size]
    E -->|Balanced| H[Use Default Sizes]
    F --> I[Calculate Spread]
    G --> I
    H --> I
    I --> J[Determine Buy/Sell Prices]
    J --> K[Check Balances and Position Limits]
    K -->|Sufficient Balances| L[Place Buy and Sell Orders]
    K -->|Insufficient Balances| M[Skip Order Placement]
    L --> N[Update Active Orders and Positions]
    M --> N
    N --> O[Wait for Refresh Interval]
    O --> B
```

MarketRushSimulator:
```mermaid
flowchart TD
    A[Start MarketRushSimulator] --> B[Initialize Participants]
    B --> C[Deposit Cash and Securities]
    C --> D[Set Wave Patterns and Momentum]
    D --> E[Begin Simulation Loop]
    
    E -->|Within Duration| F[Retrieve Market Depth]
    F -->|Depth Available| G[Determine Current Price]
    F -->|No Depth| H[Use Last Trade Price]
    G --> I[Apply Wave Pattern and Momentum]
    H --> I
    
    I --> J{Aggressive Order?}
    J -->|Yes| K[Increase Price Increment and Size]
    J -->|No| L[Use Normal Price Increment and Size]
    
    K --> M[Place Aggressive Order]
    L --> N[Place Normal Order]
    
    M --> O[Update Price and Stats]
    N --> O
    
    O -->|End of Wave| P[Move to Next Wave]
    O -->|Wave Continues| E
    
    P --> E
    
    E -->|Duration Ends or Stop Signal| Q[Stop Simulation]
    Q --> R[Shutdown Executors and Threads]
    R --> S[Log Final Stats and Exit]
```

## 9. Trade Log Replayer
[![Watch the replayer video](docs/images/screenshot_home.png)](https://youtu.be/c00UoqW__As?hd=1)
Click image to watch demo

The Trade Log Replayer is a tool for streaming historical trade logs to the visualization frontend. This allows you to analyze past trading sessions without having to re-run the simulation.

### 9.1 Features

- Replay historical trade logs through the existing visualization interface
- Control playback speed (slower or faster than real-time)
- Pause, resume, and seek to specific positions in the replay
- View candlestick, volume, and depth of market visualizations for historical data

### 9.2 Usage

1. Prepare a CSV trade log file with the following columns:
   - Trade ID: Unique identifier for each trade
   - Security ID: Identifier for the security (e.g., BTC-USD)
   - Buyer ID: Identifier for the buyer
   - Seller ID: Identifier for the seller
   - Price: Execution price
   - Size: Trade size/quantity
   - Timestamp: ISO format timestamp (YYYY-MM-DDTHH:MM:SS)

2. Run the Trade Log Replayer:
```bash
python TradeLogReplayer.py path/to/your/trade_log.csv
```

3. Optional parameters:
```bash
python TradeLogReplayer.py path/to/your/trade_log.csv --speed 2.0 --port 8085
```
   - `--speed` or `-s`: Replay speed multiplier (default: 1.0 = real-time)
   - `--port` or `-p`: Web server port (default: 8084)

4. Open your browser to the displayed URL (default: http://localhost:8084/)

5. Use the replay controls at the top of the page to:
   - Play/Pause the replay
   - Adjust replay speed
   - Seek to specific positions in the trade log

### 9.3 Sample Trade Log

A sample trade log file (`sample_trade_log.csv`) is provided for testing the replayer:

```bash
python TradeLogReplayer.py sample_trade_log.csv
```

### 9.4 Exporting Trade Logs

Trade logs can be exported from a live trading session by enabling the `EXPORT_TRADES` option in `config.py`. Exported trade logs are saved to the `logs` directory with a timestamp.

All Rights Reserved - Unidatum Integrated Products LLC