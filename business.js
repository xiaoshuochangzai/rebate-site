/*
 * @AuthorDescription: 业务
 */
var UTIL_BUSINESS = {
  copyGuide: function (selector) {
    selector = selector || '#copy-guide'

    this.copyNextElementSibling(selector)
  },
  copyNextElementSibling: function (selector) {
    var clipboard = new ClipboardJS(selector, {
      target: function (trigger) {
        return trigger.nextElementSibling
      }
    })

    UTIL_COPY.watch(clipboard, '已复制')
  },
  copyChildren: function (selector) {
    var clipboard = new ClipboardJS(selector, {
      target: function (trigger) {
        return trigger
      }
    })

    UTIL_COPY.watch(clipboard)
  },
  copyTarget: function (selector) {
    var clipboard = new ClipboardJS(selector)

    UTIL_COPY.watch(clipboard)
  },
  promote: function (pid, id, item_id, seller_id, shortTitle) {
    return COMMON_API_PRODUCT.getPromoteLink({
      pid: pid,
      id: id,
      itemid: item_id,
      seller_id: seller_id,
      title: shortTitle
    }).then(function (data) {
      return data
    })
  },
  jumpSetPid: function () {
    window.open(vmComData.vmAdminUrl + '/personal/setpid.html', '_blank')
  },
  jumpUserDetail: function (seller_id) {
    window.open(
      'https://www.haodanku.com/Bestseller/individual?id=' + seller_id,
      '_blank'
    )
  },
  countDown: function (product) {
    var startTime = product.start_time

    var startTimeStr = Number(startTime) * 1000
    var currentTimeStr = Number(new Date().getTime())

    if (startTimeStr - currentTimeStr <= 1 * 60 * 60 * 1000) {
      var timeout = 0
      var timer = setInterval(function () {
        if (timeout === 0) {
          timeout = 1000
        }

        var formatNumber = function (n) {
          n = n.toString()
          return n[1] ? n : '0' + n //补零
        }
        var cd = {},
          day,
          h,
          m,
          s
        var stamp = Number(startTime) * 1000 - Number(new Date().getTime())
        if (stamp > 0) {
          cd.d = Number(Math.floor(stamp / (24 * 3600 * 1000)))
          day = cd.d
          h = Number(formatNumber(parseInt((stamp / 1000 / 3600) % 24))) //小时
          m = formatNumber(parseInt((stamp / 1000 / 60) % 60)) //分钟
          s = formatNumber(parseInt((stamp / 1000) % 60)) //

          if (m != 0 && s >= 0 && day == 0 && h == 0) {
            // 天和小时为0
            product.notice = m + '分' + s + '秒' + '后开抢'
            return
          }

          if (s > 0 && day == 0 && h == 0 && m == 0) {
            // 天和小时和分钟都为0
            product.notice = s + '秒' + '后开抢'
            return
          }
        } else {
          product.notice = '该商品已开抢'
          clearInterval(timer)
        }
      }, timeout)
    } else {
      var formatNumber = function (n) {
        n = n.toString()
        return n[1] ? n : '0' + n //补零
      }
      var oDay = new Date(currentTimeStr).getDate()

      var date = new Date(startTimeStr) //实例一个时间对象；
      var month = date.getMonth() + 1 //由于月份是从0开始计算，所以要加1
      var day = date.getDate()
      var hour = date.getHours()
      var minute = formatNumber(date.getMinutes()) //分
      var oTime = ''

      if (day - oDay !== 0) {
        oTime = month + '月' + day + '日' + hour + '点'
      } else {
        oTime = '今日' + hour + '点' + minute + '分'
      }

      product.notice = oTime + '开抢'
    }
  },
  getSideUrlProtocol: function () {
    return window.location.protocol.substring(
      0,
      window.location.protocol.length - 1
    )
  },
  getSideUrlHost: function () {
    var hosts = window.location.host.split('.')

    return hosts[1] == 'haodanku' ? 'haodanku.com' : hosts[1] + '.' + hosts[2]
  },
  getSideUrl: function () {
    var hosts = window.location.host.split('.')

    return (
      this.getSideUrlProtocol() +
      '://publish' +
      hosts[0].slice(3) +
      '.' +
      this.getSideUrlHost()
    )
  },
  getLoginUrl: function (url) {
    url = url || encodeURIComponent(encodeURIComponent(window.location.href))
    return this.getSideUrl() + '/Login/index.html?returnurl=' + url
  },
  showLoginDialog: function () {
    headerApp && headerApp.showLoginModel && headerApp.showLoginModel()
  },
  getFavoritesByProducts: function (products) { //是否收藏
    if (!this.isLogin(false)) {
      return
    }

    var item_ids = []

    products.forEach(function (product) {
      item_ids.push(product.itemid)
    })

    return COMMON_API_PRODUCT.getFavorites({
      item_id: JSON.stringify(item_ids),
      request_head: this.getSideUrlProtocol()
    }).then(function (itemids) {
      if (itemids.length === 0) {
        return
      }

      products.forEach(function (product) {
        var val = UTIL_BUSINESS.interceptItemid(product.itemid)
        if (itemids.indexOf(val) !== -1) {
          product.favorite = true
        }
      })

      return products
    })
  },
  isLogin: function (showDialog) {
    showDialog = showDialog !== undefined ? showDialog : true

    if (headerApp && !headerApp.isLogin) {
      showDialog && this.showLoginDialog()

      return false
    }

    return true
  },
  getRegisterUrl: function () {
    return this.getLoginUrl() + '&type=register'
  },
  getResetPwdUrl: function () {
    return this.getLoginUrl() + '&type=resetPwd'
  },
  toRegister: function () {
    window.open(this.getRegisterUrl(), '_blank')
  },
  toResetPwd: function () {
    window.open(this.getResetPwdUrl(), '_blank')
  },
  getUrlParam: function () {
    var param = {}

    location.search
      .slice(1)
      .split('&')
      .forEach(function (item) {
        var hash = item.split('=')
        param[hash[0]] = hash[1]
      })

    return param
  },
  getCookie: function (cname) {
    var name = cname + '='
    var ca = document.cookie.split(';')
    for (var i = 0; i < ca.length; i++) {
      var c = ca[i].trim()
      if (c.indexOf(name) == 0) {
        return c.substring(name.length, c.length)
      }
    }
    return ''
  },
  setCookie: function (cname, cvalue, exdays) {
    var expires = 'expires=' + new Date(exdays).toGMTString()
    document.cookie = cname + '=' + cvalue + '; ' + expires
  },
  getUserByCookie: function () {
    return {
      mobile: this.getCookie('rem_phone'),
      checkedRememberPwd: Boolean(Number(this.getCookie('rem_pwd'))),
      password: '********'
    }
  },
  verifyCookieUserPassword: function (password) {
    var user = this.getUserByCookie()

    return user.checkedRememberPwd && user.password === '********' && user.password === password
  },
  addParameter: function (param, value) {
    var param_value = "";
    var connector = "";
    var add_param = param + "=" + value;

    var current_href = window.location.href;
    if (current_href.indexOf("?") >= 0) {
      connector = "&";
    } else {
      connector = "?";
    }
    if (current_href.indexOf(param) >= 0) {	//如果参数存在，就替换此参数
      param_value = vmgeturlparam(param);
      var pre_param = param + "=" + param_value;
      current_href = current_href.replace(pre_param, add_param);
    } else {
      current_href += connector + add_param;
    }
    // window.location.href = current_href;
    history.pushState("", "", current_href);
    function vmgeturlparam(name) {
      var reg = new RegExp("(^|&)" + name + "=([^&]*)(&|$)"); //构造一个含有目标参数的正则表达式对象
      var r = window.location.search.substr(1).match(reg);  //匹配目标参数
      if (r != null) return r[2]; return null; //返回参数值
    }
  },
  delParameter: function (ref) {
    var url = window.location.href;
    var str = "";
    if (url.indexOf('?') != -1) {
      str = url.substr(url.indexOf('?') + 1);
    } else {
      history.pushState("", "", url);
    }
    var arr = "";
    var returnurl = "";
    if (str.indexOf('&') != -1) {
      arr = str.split('&');
      for (i in arr) {
        if (arr[i].split('=')[0] != ref) {
          returnurl = returnurl + arr[i].split('=')[0] + "=" + arr[i].split('=')[1] + "&";
        }
      }
      var url = url.substr(0, url.indexOf('?')) + "?" + returnurl.substr(0, returnurl.length - 1);
      history.pushState("", "", url);
    }
    else {
      arr = str.split('=');
      if (arr[0] == ref) {
        var link = url.substr(0, url.indexOf('?'));
        history.pushState("", "", link);
      } else {
        history.pushState("", "", url);
      }
    }
  },
  saveImg: function (img) {  //保存图片
    var vmimg = img.replace(/^https|http/i, vmHTTPurl);
    window.URL = window.URL || window.webkitURL;
    var xhr = new XMLHttpRequest();
    xhr.open("get", vmimg, true);
    xhr.responseType = "blob";
    xhr.onload = function () {
      if (this.status == 200) {
        var blob = this.response;
        var oFileReader = new FileReader();
        oFileReader.onloadend = function (e) {
          var base64 = e.target.result;
          var a = document.createElement('a');
          var event = new MouseEvent('click');
          a.download = Math.round(Math.random() * 10000) || '图片';
          a.href = base64;
          a.dispatchEvent(event);
        };
        oFileReader.readAsDataURL(blob);
      }
    }
    xhr.send();
  },
  openTaobao: function (itemid) {  //跳淘宝
    window.open(this.backTaobao(itemid))
  },
  backTaobao: function (itemid) { //返回淘宝链接
    if (this.isJmItemid(itemid)) {
      return 'https://uland.TaoBao.com/item/edetail?id=' + itemid;
    }
    return "https://detail.tmall.com/item.htm?id=" + itemid;
  },
  interceptItemid: function (itemid) { //截取itemid
    if (this.isJmItemid(itemid)) {
      return itemid.substring(itemid.indexOf("-") + 1);
    }
    return itemid
  },
  isJmItemid: function (itemid) {  //是否为加密串
    return isNaN(Number(itemid));
    // return /[A-Za-z0-9]{13,25}-[A-Za-z0-9]{13,25}/.test(itemid)
  },
  getItemid: function (txt, isBack) {  //正则匹配itemid
    var x = /[?&]id=([0-9a-zA-Z-]+)/
    var y = /^[0-9]{11,13}$|^[0-9a-zA-Z]*-[0-9a-zA-Z]*$/
    if (txt.match(x)) {
      return txt.match(x)[1]
    } else if(txt.match(y)) {
      return txt.match(y)[0]
    }
    return isBack ? false : txt;
  }
}