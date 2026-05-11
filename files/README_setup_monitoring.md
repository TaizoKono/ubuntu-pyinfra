# Ansibleによる監視設定

※ sudoにPWが必要なときは`--ask-become-pass`を付ける
~~~sh
ansible-playbook -i hosts site.yaml --ask-become-pass
~~~