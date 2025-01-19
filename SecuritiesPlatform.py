# Core Domain Models

from datetime import datetime
from typing import List, Dict, Optional
from decimal import Decimal
from enum import Enum
import uuid


class SecurityType(Enum):
    EQUITY = "equity"
    BOND = "bond"
    ETF = "etf"
    DERIVATIVE = "derivative"


class Security:
    def __init__(
            self,
            id: str,
            cusip: str,
            isin: str,
            security_type: SecurityType,
            ticker: str,
            name: str,
            current_price: Decimal
    ):
        self.id = id
        self.cusip = cusip
        self.isin = isin
        self.security_type = security_type
        self.ticker = ticker
        self.name = name
        self.current_price = current_price
        self.last_updated = datetime.utcnow()


class Position:
    def __init__(
            self,
            security_id: str,
            quantity: Decimal,
            custodian_id: str,
            owner_id: str,
            available_to_lend: bool = True
    ):
        self.id = str(uuid.uuid4())
        self.security_id = security_id
        self.quantity = quantity
        self.custodian_id = custodian_id
        self.owner_id = owner_id
        self.available_to_lend = available_to_lend
        self.created_at = datetime.utcnow()


class LoanAgreement:
    def __init__(
            self,
            lender_id: str,
            borrower_id: str,
            security_id: str,
            quantity: Decimal,
            rate: Decimal,
            start_date: datetime,
            end_date: datetime,
            collateral_amount: Decimal
    ):
        self.id = str(uuid.uuid4())
        self.lender_id = lender_id
        self.borrower_id = borrower_id
        self.security_id = security_id
        self.quantity = quantity
        self.rate = rate
        self.start_date = start_date
        self.end_date = end_date
        self.collateral_amount = collateral_amount
        self.status = "active"
        self.created_at = datetime.utcnow()


# Repository Layer

class SecurityRepository:
    async def get_security(self, security_id: str) -> Optional[Security]:
        pass

    async def update_price(self, security_id: str, new_price: Decimal) -> bool:
        pass

    async def get_securities_by_type(self, security_type: SecurityType) -> List[Security]:
        pass


class PositionRepository:
    async def get_positions_by_owner(self, owner_id: str) -> List[Position]:
        pass

    async def get_available_positions(self, security_id: str) -> List[Position]:
        pass

    async def update_position(self, position_id: str, quantity: Decimal) -> bool:
        pass


class LoanAgreementRepository:
    async def create_loan(self, loan: LoanAgreement) -> str:
        pass

    async def get_active_loans(self, participant_id: str) -> List[LoanAgreement]:
        pass

    async def terminate_loan(self, loan_id: str) -> bool:
        pass


# Service Layer

class PricingService:
    def __init__(self, security_repository: SecurityRepository):
        self.security_repository = security_repository

    async def update_security_price(self, security_id: str, price: Decimal):
        """Updates security price and broadcasts to network"""
        await self.security_repository.update_price(security_id, price)
        await self._broadcast_price_update(security_id, price)

    async def _broadcast_price_update(self, security_id: str, price: Decimal):
        """Broadcasts price updates to the decentralized network"""
        # Implementation for broadcasting to network nodes
        pass

    async def get_market_value(self, security_id: str, quantity: Decimal) -> Decimal:
        """Calculates market value based on current price"""
        security = await self.security_repository.get_security(security_id)
        return security.current_price * quantity if security else Decimal(0)


class LendingService:
    def __init__(
            self,
            position_repository: PositionRepository,
            loan_repository: LoanAgreementRepository,
            pricing_service: PricingService
    ):
        self.position_repository = position_repository
        self.loan_repository = loan_repository
        self.pricing_service = pricing_service

    async def create_loan_agreement(
            self,
            lender_id: str,
            borrower_id: str,
            security_id: str,
            quantity: Decimal,
            rate: Decimal,
            duration_days: int
    ) -> Optional[str]:
        """Creates a new loan agreement if positions are available"""
        available_positions = await self.position_repository.get_available_positions(security_id)

        if not self._verify_available_quantity(available_positions, quantity):
            return None

        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=duration_days)

        # Calculate collateral based on current market value plus margin
        market_value = await self.pricing_service.get_market_value(security_id, quantity)
        collateral_amount = market_value * Decimal('1.02')  # 102% collateral

        loan = LoanAgreement(
            lender_id=lender_id,
            borrower_id=borrower_id,
            security_id=security_id,
            quantity=quantity,
            rate=rate,
            start_date=start_date,
            end_date=end_date,
            collateral_amount=collateral_amount
        )

        return await self.loan_repository.create_loan(loan)

    def _verify_available_quantity(self, positions: List[Position], required_quantity: Decimal) -> bool:
        """Verifies if enough quantity is available for loan"""
        total_available = sum(p.quantity for p in positions if p.available_to_lend)
        return total_available >= required_quantity


# API Layer

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class CreateLoanRequest(BaseModel):
    lender_id: str
    borrower_id: str
    security_id: str
    quantity: Decimal
    rate: Decimal
    duration_days: int


@app.post("/api/v1/loans")
async def create_loan(request: CreateLoanRequest):
    loan_id = await lending_service.create_loan_agreement(
        request.lender_id,
        request.borrower_id,
        request.security_id,
        request.quantity,
        request.rate,
        request.duration_days
    )

    if not loan_id:
        raise HTTPException(status_code=400, detail="Insufficient available positions")

    return {"loan_id": loan_id}


@app.get("/api/v1/positions/{owner_id}")
async def get_positions(owner_id: str):
    positions = await position_repository.get_positions_by_owner(owner_id)
    return {"positions": positions}


@app.get("/api/v1/loans/{participant_id}")
async def get_active_loans(participant_id: str):
    loans = await loan_repository.get_active_loans(participant_id)
    return {"loans": loans}


# Requirements (save as requirements.txt):
"""
fastapi==0.68.0
uvicorn==0.15.0
pydantic==1.8.2
asyncpg==0.24.0  # for PostgreSQL support
python-dotenv==0.19.0
"""


# Decentralized Network Node

class NetworkNode:
    def __init__(self, node_id: str, pricing_service: PricingService):
        self.node_id = node_id
        self.pricing_service = pricing_service
        self.connected_nodes: List[str] = []

    async def broadcast_price_update(self, security_id: str, price: Decimal):
        """Broadcasts price updates to connected nodes"""
        for node_id in self.connected_nodes:
            await self._send_price_update(node_id, security_id, price)

    async def receive_price_update(self, security_id: str, price: Decimal, source_node: str):
        """Handles incoming price updates from other nodes"""
        # Validate price update
        if await self._validate_price_update(security_id, price):
            await self.pricing_service.update_security_price(security_id, price)
            # Relay to other nodes excluding source
            await self._relay_price_update(security_id, price, source_node)

    async def _validate_price_update(self, security_id: str, price: Decimal) -> bool:
        """Validates price updates against threshold and consensus"""
        # Implementation for price validation
        pass


if __name__ == "__main__":
    import uvicorn
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get configuration from environment variables
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    # Run the FastAPI application
    uvicorn.run("SecuritiesPlatform:app", host=host, port=port, reload=True)