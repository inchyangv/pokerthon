from pydantic import BaseModel


class SitRequest(BaseModel):
    seat_no: int | None = None
