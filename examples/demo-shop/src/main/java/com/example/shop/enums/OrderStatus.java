package com.example.shop.enums;

/** 订单状态 */
public enum OrderStatus {
    WAIT_PAY(10, "待支付"),
    PAID(20, "已支付"),
    SHIPPED(30, "已发货"),
    CANCELLED(-1, "已取消");

    private final int code;
    private final String label;

    OrderStatus(int code, String label) {
        this.code = code;
        this.label = label;
    }
}
