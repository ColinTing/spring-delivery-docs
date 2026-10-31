package com.example.shop.common;

import com.baomidou.mybatisplus.annotation.*;
import java.time.LocalDateTime;

public abstract class BaseEntity {
    /** 创建时间 */
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    /** 更新时间 */
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
    /** 逻辑删除 0 正常 1 删除 */
    @TableLogic
    private Integer deleted;
}
