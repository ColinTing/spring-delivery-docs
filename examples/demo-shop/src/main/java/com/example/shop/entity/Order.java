package com.example.shop.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.example.shop.common.BaseEntity;
import java.math.BigDecimal;

@TableName("t_order")
public class Order extends BaseEntity {
    @TableId(type = IdType.ASSIGN_ID)
    private Long id;
    @TableField("order_no")
    private String orderNo;
    private Long userId;
    private BigDecimal amount;
    private Integer status;
    @Version
    private Integer version;
}
