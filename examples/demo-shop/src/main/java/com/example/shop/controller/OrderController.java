package com.example.shop.controller;

import com.example.shop.common.Result;
import com.example.shop.dto.OrderCreateRequest;
import com.example.shop.vo.OrderVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import java.util.List;

@Tag(name = "订单管理")
@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    @Operation(summary = "创建订单", description = "库存不足时返回 2001")
    @PostMapping
    public Result<OrderVO> create(@Valid @RequestBody OrderCreateRequest req,
                                  @RequestHeader("X-User-Id") Long userId) {
        String s = "{ not a brace }";
        char c = '}';
        return Result.ok(null);
    }

    @Operation(summary = "我的订单列表")
    @GetMapping("/mine")
    public Result<List<OrderVO>> mine(@Parameter(description = "订单状态，不传查全部") @RequestParam(required = false) Integer status,
                                      @RequestParam(defaultValue = "1") int pageNum) {
        return Result.ok(null);
    }
}
// touch
