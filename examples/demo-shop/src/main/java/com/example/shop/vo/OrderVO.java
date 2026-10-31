package com.example.shop.vo;

import com.example.shop.enums.OrderStatus;
import io.swagger.v3.oas.annotations.media.Schema;
import java.math.BigDecimal;

@Schema(description = "订单信息")
public class OrderVO {
    @Schema(description = "订单号", example = "202610310001")
    private String orderNo;
    @Schema(description = "订单金额(元)")
    private BigDecimal amount;
    @Schema(description = "订单状态")
    private OrderStatus status;
}
