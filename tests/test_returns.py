# Unit tests for the return rule engine (src/returns.py)
# Run from the project root: python -m unittest discover tests -v
import unittest
from dataclasses import replace
from datetime import date

from src.returns import (
    ALREADY_CLOSED, DUPLICATE_REQUEST, ELIGIBLE, IN_TRANSIT, NEEDS_HUMAN,
    NOT_DELIVERED_CANCELLABLE, NOT_ELIGIBLE_WINDOW, NOT_FOUND,
    PENDING_REVIEW, PENDING_SENIOR,
    Item, OrderFacts, Payment, check_return_eligibility,
)


def make_order(**changes):
    """A normal delivered order (day 5, on time); tests change only what they need."""
    base = OrderFacts(
        order_id="test-order",
        status="delivered",
        purchase_date=date(2018, 8, 10),
        delivered_date=date(2018, 8, 27),       # 5 days before 2018-09-01
        estimated_date=date(2018, 8, 30),       # delivered before the estimate
        carrier_date=date(2018, 8, 14),
        items=[Item(price=100.0, freight_value=20.0, shipping_limit_date=date(2018, 8, 15))],
        payments=[Payment("credit_card", 120.0)],
    )
    return replace(base, **changes)


class TestStatusRules(unittest.TestCase):

    def test_r1_order_of_another_customer(self):
        d = check_return_eligibility(None, "changed_mind")
        self.assertEqual((d.code, d.rule), (NOT_FOUND, "R1"))

    def test_r0_order_placed_today_or_later(self):
        for day in [date(2018, 9, 1), date(2018, 9, 3)]:
            with self.subTest(purchase_date=day):
                d = check_return_eligibility(make_order(purchase_date=day), "changed_mind")
                self.assertEqual((d.code, d.rule), (NOT_FOUND, "R0"))

    def test_r2_not_delivered(self):
        for status in ["created", "approved", "invoiced", "processing"]:
            with self.subTest(status=status):
                d = check_return_eligibility(make_order(status=status, delivered_date=None), "changed_mind")
                self.assertEqual((d.code, d.rule), (NOT_DELIVERED_CANCELLABLE, "R2"))

    def test_r3_shipped(self):
        d = check_return_eligibility(make_order(status="shipped", delivered_date=None), "changed_mind")
        self.assertEqual((d.code, d.rule), (IN_TRANSIT, "R3"))

    def test_r3_delivered_after_today(self):
        # Boundary test from the brief: delivered on 2018-09-05 -> IN_TRANSIT
        d = check_return_eligibility(make_order(delivered_date=date(2018, 9, 5)), "damaged")
        self.assertEqual((d.code, d.rule), (IN_TRANSIT, "R3"))

    def test_r4_closed(self):
        for status in ["canceled", "unavailable"]:
            with self.subTest(status=status):
                d = check_return_eligibility(make_order(status=status, delivered_date=None), "changed_mind")
                self.assertEqual((d.code, d.rule), (ALREADY_CLOSED, "R4"))

    def test_r5_delivered_without_date(self):
        d = check_return_eligibility(make_order(delivered_date=None), "changed_mind")
        self.assertEqual((d.code, d.rule), (NEEDS_HUMAN, "R5"))

    def test_r11_existing_request(self):
        for status in ["PENDING_REVIEW", "PENDING_SENIOR", "APPROVED", "REJECTED"]:
            with self.subTest(existing=status):
                d = check_return_eligibility(make_order(existing_request_statuses=[status]), "changed_mind")
                self.assertEqual((d.code, d.rule), (DUPLICATE_REQUEST, "R11"))


class TestWindowRules(unittest.TestCase):
    # Boundary tests from the brief (section 6.1)

    def check(self, delivered, reason, expected_code, expected_days):
        d = check_return_eligibility(make_order(delivered_date=delivered), reason)
        self.assertEqual(d.code, expected_code)
        self.assertEqual(d.days_since_delivery, expected_days)

    def test_r6_day_0(self):
        self.check(date(2018, 9, 1), "changed_mind", ELIGIBLE, 0)

    def test_r6_day_14(self):
        self.check(date(2018, 8, 18), "changed_mind", ELIGIBLE, 14)

    def test_r6_day_15(self):
        self.check(date(2018, 8, 17), "changed_mind", NOT_ELIGIBLE_WINDOW, 15)

    def test_r6_late_reason_uses_14_days(self):
        self.check(date(2018, 8, 17), "late", NOT_ELIGIBLE_WINDOW, 15)

    def test_r7_day_30(self):
        self.check(date(2018, 8, 2), "damaged", ELIGIBLE, 30)

    def test_r7_day_31(self):
        self.check(date(2018, 8, 1), "wrong_item", NOT_ELIGIBLE_WINDOW, 31)


class TestAmountRules(unittest.TestCase):

    def test_r8_changed_mind_refunds_price_only(self):
        d = check_return_eligibility(make_order(), "changed_mind")
        self.assertEqual(d.refund_amount, 100.0)

    def test_r8_damaged_refunds_price_and_freight(self):
        d = check_return_eligibility(make_order(), "damaged")
        self.assertEqual(d.refund_amount, 120.0)

    def test_r8_not_eligible_without_r9_is_zero(self):
        d = check_return_eligibility(make_order(delivered_date=date(2018, 8, 10)), "changed_mind")
        self.assertEqual((d.code, d.refund_amount, d.approval_level), (NOT_ELIGIBLE_WINDOW, 0.0, None))

    def test_r9_flag_at_10_days_late(self):
        order = make_order(delivered_date=date(2018, 8, 27), estimated_date=date(2018, 8, 17))
        d = check_return_eligibility(order, "changed_mind")
        self.assertTrue(d.freight_refund)
        self.assertEqual(d.refund_amount, 120.0)   # price + freight

    def test_r9_no_flag_at_9_days_late(self):
        order = make_order(delivered_date=date(2018, 8, 27), estimated_date=date(2018, 8, 18))
        d = check_return_eligibility(order, "changed_mind")
        self.assertFalse(d.freight_refund)
        self.assertEqual(d.refund_amount, 100.0)

    def test_r9_outside_window_freight_only(self):
        # Day 20: outside the 14-day window, but delivered 12 days late -> freight only
        order = make_order(delivered_date=date(2018, 8, 12), estimated_date=date(2018, 7, 31))
        d = check_return_eligibility(order, "changed_mind")
        self.assertEqual(d.code, NOT_ELIGIBLE_WINDOW)
        self.assertEqual(d.refund_amount, 20.0)
        self.assertEqual(d.approval_level, PENDING_REVIEW)

    def test_r9_after_30_days_nothing(self):
        order = make_order(delivered_date=date(2018, 7, 31), estimated_date=date(2018, 7, 15))
        d = check_return_eligibility(order, "changed_mind")
        self.assertEqual((d.code, d.refund_amount), (NOT_ELIGIBLE_WINDOW, 0.0))

    def test_r10_500_is_review(self):
        order = make_order(items=[Item(price=500.0, freight_value=10.0)])
        d = check_return_eligibility(order, "changed_mind")
        self.assertEqual((d.refund_amount, d.approval_level), (500.0, PENDING_REVIEW))

    def test_r10_above_500_is_senior(self):
        order = make_order(items=[Item(price=500.01, freight_value=10.0)])
        d = check_return_eligibility(order, "changed_mind")
        self.assertEqual(d.approval_level, PENDING_SENIOR)

    def test_r10_freight_counts_toward_threshold(self):
        # 490 + 20 freight = 510 for a damaged item -> senior
        order = make_order(items=[Item(price=490.0, freight_value=20.0)])
        d = check_return_eligibility(order, "damaged")
        self.assertEqual((d.refund_amount, d.approval_level), (510.0, PENDING_SENIOR))

    def test_r10_multiple_items_are_summed(self):
        order = make_order(items=[Item(price=300.0, freight_value=10.0), Item(price=250.0, freight_value=10.0)])
        d = check_return_eligibility(order, "changed_mind")
        self.assertEqual((d.refund_amount, d.approval_level), (550.0, PENDING_SENIOR))

    def test_r12_voucher_share(self):
        # 30 of 120 paid by voucher -> 25% of the refund goes back as voucher
        order = make_order(payments=[Payment("voucher", 30.0), Payment("credit_card", 90.0)])
        d = check_return_eligibility(order, "damaged")   # refund 120
        self.assertEqual(d.voucher_amount, 30.0)

    def test_r12_no_voucher(self):
        d = check_return_eligibility(make_order(), "damaged")
        self.assertEqual(d.voucher_amount, 0.0)

    def test_r13_seller_late(self):
        order = make_order(carrier_date=date(2018, 8, 16))   # limit is 2018-08-15
        d = check_return_eligibility(order, "changed_mind")
        self.assertTrue(d.seller_late)

    def test_r13_seller_on_time(self):
        order = make_order(carrier_date=date(2018, 8, 15))   # same day is not late
        d = check_return_eligibility(order, "changed_mind")
        self.assertFalse(d.seller_late)


class TestInput(unittest.TestCase):

    def test_unknown_reason_is_rejected(self):
        with self.assertRaises(ValueError):
            check_return_eligibility(make_order(), "too_expensive")


if __name__ == "__main__":
    unittest.main()