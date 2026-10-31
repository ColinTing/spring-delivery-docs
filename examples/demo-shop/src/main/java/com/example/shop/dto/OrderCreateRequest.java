package com.example.shop.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import javax.validation.Valid;
import javax.validation.constraints.*;
import java.util.List;

@Schema(description = "下单请求")
public record OrderCreateRequest(
        @Schema(description = "收货地址ID", requiredMode = Schema.RequiredMode.REQUIRED) @NotNull Long addressId,
        @Schema(description = "商品明细") @NotEmpty @Valid List<Item> items,
        @Schema(description = "买家备注", example = "请尽快发货") @Size(max = 200) String remark) {

    @Schema(description = "订单商品")
    public record Item(@NotNull Long skuId, @Min(1) @Max(99) Integer quantity) {
    }
}
