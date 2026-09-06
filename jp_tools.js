// 加密网站 https://www.e-learn.cn/tools/js-encrypt

// 点击转链
$(".transferrinButton").bind('click', function () {
    let that = this;
    $(that).addClass('notclick');
    $(that).css('background', '#ccc');
    let content = $(".toolContent_left").val();
    let rid = 0;
    if($("#toolRid-select option:selected").val()){
        rid = $("#toolRid-select option:selected").val();
    }else{
        rid = $(".toolRid").val();
    }
    let data = {
        content: content,
        rid:rid,
        t: Date.now()
    };
    $.ajax({
        url: '/tools/chain_link',
        data: data,
        type: 'post',
        dataType: 'json',
        success: function (resp) {
            console.log(resp);
            if (resp.code == '0') {
                if (resp.images.length > 0) {
                    $(".toolContent_right").text('');
                    $(".toolContent_right").append(`<img src="${resp.images[0]}" style="width: 200px; height: 200px; display: block;" />`);
                    $(".toolContent_right").append(resp.data);

                } else {
                    $(".toolContent_right").text('');
                    $(".toolContent_right").text(resp.data);
                }
            } else {
                Quattro.toast('msg', resp.msg, {
                    'time': 2,
                    'unique': 'toast'
                });
            }
            $(that).removeClass('notclick');
            $(that).css('background', 'linear-gradient( 90deg , #FD5272 0%, #FC7759 100%)');
        },
        error: function (err) {
            Quattro.toast('msg', '系统错误', {
                'time': 2,
                'unique': 'toast'
            });
        }
    })
});



// 点击线报转链
$(".tipButton").bind('click', function () {

    
    let that = this;
    $(that).addClass('notclick');
    $(that).css('background', '#ccc');
    let content = $(".toolContent_left").val();
    let rid = 0;
    if($("#toolRid-select option:selected").val()){
        rid = $("#toolRid-select option:selected").val();
    }else{
        rid = $(".toolRid").val();
    }
    let data = {
        content: content,
        rid:rid,
        t: Date.now()
    };
    $.ajax({
        url: '/tools/atip_link',
        data: data,
        type: 'post',
        dataType: 'json',
        success: function (resp) {
            console.log(resp);
            if (resp.code == '0') {
                if (resp.images.length > 0) {
                    $(".toolContent_right").text('');
                    $(".toolContent_right").append(`<img src="${resp.images[0]}" style="width: 200px; height: 200px; display: block;" />`);
                    $(".toolContent_right").append(resp.data);

                } else {
                    $(".toolContent_right").text('');
                    $(".toolContent_right").text(resp.data);
                }
            } else {
                Quattro.toast('msg', resp.msg, {
                    'time': 2,
                    'unique': 'toast'
                });
            }
            $(that).removeClass('notclick');
            $(that).css('background', 'linear-gradient( 90deg , #FD5272 0%, #FC7759 100%)');
        },
        error: function (err) {
            Quattro.toast('msg', '系统错误', {
                'time': 2,
                'unique': 'toast'
            });
        }
    })
});