package com.example.shop.common;

import lombok.Data;
import java.util.List;

@Data
public class PageResult<T> {
    private Long total; // 总条数
    private List<T> records; // 当前页数据
}
