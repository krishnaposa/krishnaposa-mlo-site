# finance.py
def mortgage_pi(price, down, rate_pct, years):
    loan = price - down
    r = rate_pct/100/12
    n = years*12
    return round(loan * r * (1+r)**n / ((1+r)**n - 1), 2)