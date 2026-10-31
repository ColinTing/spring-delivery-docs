package com.example.shop.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.example.shop.common.BaseEntity;
import lombok.Data;

/**
 * 用户表
 */
@Data
@TableName("t_user")
public class User extends BaseEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    /** 用户名 */
    private String username;
    /** 密码(BCrypt) */
    private String password;
    private String mobile; // 手机号
    /** 状态 1 启用 0 禁用 */
    private Integer status;
    @TableField(exist = false)
    private String roleName;
}
