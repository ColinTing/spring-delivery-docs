package com.example.shop.dto;

import lombok.Data;

@Data
public class UserQuery {
    /** 页码，从 1 开始 */
    private Integer pageNum = 1;
    /** 每页条数 */
    private Integer pageSize = 10;
    /** 用户名模糊匹配 */
    private String keyword;
    private Integer status;
}
